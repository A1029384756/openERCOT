{
  description = "Python 3.11 Devshell and Builds";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };

        commonArgs = with pkgs.python311Packages; [
          numpy
          pandas
          python-dotenv
          matplotlib
          requests
        ];

        pyEnv = pkgs.python311.withPackages (ps:
          with pkgs.python311Packages;
          commonArgs ++ [
            (
              buildPythonPackage rec {
                pname = "pypsa";
                version = "0.26.2";
                src = fetchPypi {
                  inherit pname version;
                  hash = "sha256-uq/ZAF9InBNU4HBKKTLZPZJUyxBoDet70cIkCOCvw9w=";
                };
                propagatedBuildInputs = commonArgs ++ [
                  pkgs.python311Packages.pip
                  pkgs.python311Packages.validators
                  pkgs.python311Packages.deprecation
                  pkgs.python311Packages.networkx
                  pkgs.python311Packages.geopandas
                  pkgs.python311Packages.numpy
                  pkgs.python311Packages.scipy
                  pkgs.python311Packages.xarray
                  pkgs.python311Packages.netcdf4
                  pkgs.python311Packages.tables
                  pkgs.python311Packages.pyomo
                ];
              }
            )
          ]);
      in
      with pkgs;
      {
        devShells.default = mkShell {
          packages = [
            pyEnv
            pyright
          ];
        };
      }
    );
}
