{
  description = "Python 3.11 Devshell and Builds";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-23.11";
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
          pip
          validators
          deprecation
          networkx
          geopandas
          numpy
          scipy
          xarray
          netcdf4
          tables
          pyomo
          tqdm
          dask
          bottleneck
          openpyxl
        ];

        linopy = pkgs.python311Packages.buildPythonPackage rec {
          pname = "linopy";
          version = "0.3.2";

          src = pkgs.python311Packages.fetchPypi {
            inherit pname version;
            hash = "sha256-CPsdbOZzVJzWbu5lQxe7g/+fAb0gOKITvq0lXB+Okw0=";
          };

          nativeBuildInputs = [
            pkgs.which
          ];

          propagatedBuildInputs = commonArgs;
        };

        pypsa = pkgs.python311Packages.buildPythonPackage rec {
          pname = "pypsa";
          version = "0.26.2";
          format = "pyproject";

          src = pkgs.python311Packages.fetchPypi {
            inherit pname version;
            hash = "sha256-uq/ZAF9InBNU4HBKKTLZPZJUyxBoDet70cIkCOCvw9w=";
          };

          propagatedBuildInputs = commonArgs ++ [ linopy ];
        };

        pyEnv = pkgs.python311.withPackages (ps:
          with pkgs.python311Packages;
          [
            pypsa
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
