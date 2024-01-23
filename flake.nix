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
          version = "0.2.6";

          src = pkgs.python311Packages.fetchPypi {
            inherit pname version;
            hash = "sha256-JOSGfzU5Ejx0WHGUzQecRfUn9f0L4e0B8e8f6q/KpnM=";
          };

          nativeBuildInputs = [
            pkgs.which
          ];

          propagatedBuildInputs = commonArgs;
        };

        highspy = pkgs.python311Packages.buildPythonPackage rec {
          pname = "highspy";
          version = "1.5.3";
          format = "wheel";

          src =
            let
              computePath = system: (
                if system == "x86_64-linux" then
                  "manylinux_2_17_x86_64.manylinux2014_x86_64"
                else if system == "aarch64-linux" then
                  "manylinux_2_17_aarch64.manylinux2014_aarch64"
                else if system == "x86_64-darwin" then
                  "macosx_10_9_x86_64"
                else if system == "aarch64-darwin" then
                  "macosx_11_0_arm64"
                else throw "Unsupported system: ${system}"
              );
            in
            builtins.fetchurl {
              url = "https://files.pythonhosted.org/packages/31/65/41e1b4774a999bf72301ca4146bc5050cd803ef46dfd7bcc12a3da192cbb/highspy-1.5.3-cp311-cp311-${computePath(system)}.whl";
              sha256 = "sha256:0ya5ydxkxan19a8q16hz766b131wjh7dqiicfwdmkfv1hcchxk61";
            };
        };

        pypsa = pkgs.python311Packages.buildPythonPackage rec {
          pname = "pypsa";
          version = "0.26.2";
          format = "pyproject";

          src = pkgs.python311Packages.fetchPypi {
            inherit pname version;
            hash = "sha256-uq/ZAF9InBNU4HBKKTLZPZJUyxBoDet70cIkCOCvw9w=";
          };

          propagatedBuildInputs = commonArgs ++ [ linopy highspy ];
        };

        pyEnv = pkgs.python311.withPackages (ps:
          with pkgs.python311Packages;
          [
            pypsa
          ]);
      in
      with pkgs;
      {
        packages.default = pyEnv;
        devShells.default = mkShell {
          packages = [
            pyEnv
            pyright
            ruff
          ];
        };
      }
    );
}
