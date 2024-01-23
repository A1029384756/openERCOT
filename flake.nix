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
          python-lsp-ruff
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
              getUrlInfo = system: (
                if system == "x86_64-linux" then
                  {
                    url = "https://files.pythonhosted.org/packages/31/65/41e1b4774a999bf72301ca4146bc5050cd803ef46dfd7bcc12a3da192cbb/highspy-1.5.3-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl";
                    sha256 = "sha256:0ya5ydxkxan19a8q16hz766b131wjh7dqiicfwdmkfv1hcchxk61";
                  }
                else if system == "aarch64-linux" then
                  {
                    url = "https://files.pythonhosted.org/packages/e9/96/181e035721a3382fdef9c9135d6f2f3bcfbb56a714d7b51599038755d471/highspy-1.5.3-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl";
                    sha256 = "sha256:1gw8zswwk8136jkif4irx7i6v8dissi2aild73z05ijg74s0z0l6";
                  }
                else if system == "aarch64-darwin" then
                  {
                    url = "https://files.pythonhosted.org/packages/51/ce/8be1539eaffb4f66fecb08dd636a43093811b54aacbb037ab45e9ab4d15d/highspy-1.5.3-cp311-cp311-macosx_11_0_arm64.whl";
                    sha256 = "sha256:0hqshscqgay6glnwpiy9z87v18sdqy18r8dsllrw9j8q84whg3rw";
                  }
                else if system == "x86_64-darwin" then
                  {
                    url = "https://files.pythonhosted.org/packages/c3/38/12839b494a28bd30e562f91794b7e64c30853caa224996e304c7b21ce988/highspy-1.5.3-cp311-cp311-macosx_10_9_x86_64.whl";
                    sha256 = "sha256:07v2yd2zhriwrbczx28zalpc3gkr0qjd5lfhd8lasqlaqi798r07";
                  }
                else throw "Unsupported system: ${system}"
              );
              urlInfo = getUrlInfo (system);
            in
            builtins.fetchurl {
              url = urlInfo.url;
              sha256 = urlInfo.sha256;
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
        devShells = {
          default = mkShell {
            buildInputs = [
              pypsa
              highspy
              linopy
            ] ++ commonArgs;
            packages = [
              pyright
              ruff
            ];
          };

          formatting = mkShell {
            packages = [
              ruff
            ];
          };
        };
      }
    );
}
